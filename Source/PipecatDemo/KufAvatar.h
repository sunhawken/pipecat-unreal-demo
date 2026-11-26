// KufAvatar: third-person test avatar for the rigged KUF models (Ellen by default): WASD move, mouse look, 1-0 / Q / E to play every imported animation.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/Pawn.h"
#include "KufAvatar.generated.h"

class UAnimSequence;
class UCameraComponent;
class USkeletalMeshComponent;
class USpringArmComponent;

UCLASS()
class AKufAvatar : public APawn
{
	GENERATED_BODY()

public:
	AKufAvatar();

	/** Folder holding the imported SkeletalMesh + its AnimSequences (see /Game/KUF/Rigged/Units/<mesh>/SkeletalMeshes). */
	UPROPERTY(EditAnywhere, Category = "KUF")
	FString MeshFolder = TEXT("/Game/KUF/Rigged/Units/C_HS_IR/SkeletalMeshes");

	UPROPERTY(EditAnywhere, Category = "KUF")
	FString MeshName = TEXT("C_HS_IR");

	UPROPERTY(EditAnywhere, Category = "KUF")
	float MoveSpeed = 500.f;

	/** The decoded meshes face an unknown axis after the glTF axis conversion; F rotates this by 90 degrees at runtime. */
	UPROPERTY(EditAnywhere, Category = "KUF")
	float MeshYawOffset = 90.f;

	/** Interchange imports the decoded glTF files at x100 (it assumes meters); 0.01 restores the game's own centimetres. */
	UPROPERTY(EditAnywhere, Category = "KUF")
	float MeshScale = 0.01f;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USkeletalMeshComponent> Mesh;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USpringArmComponent> Boom;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UCameraComponent> Camera;

	UPROPERTY()
	TArray<TObjectPtr<UAnimSequence>> Anims;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaTime) override;

private:
	int32 Current = 0;
	float CamYaw = 0.f, CamPitch = -20.f, Dist = 450.f;
	bool bHaveGround = false;
	bool bSelfTest = false;
	float SelfTestTime = 0.f;
	int32 ShotStep = -1;

	void PlayIndex(int32 Index);
	float GroundZ(const FVector& At, bool& bHit) const;
};

UCLASS()
class AKufAvatarGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AKufAvatarGameMode();
};
