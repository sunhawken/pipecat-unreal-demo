// KufPlay: the playable layer of the Kingdom Under Fire port. Units come from the decoded stage files (job, position); the combat numbers below
// are PLACEHOLDERS until the real rules are decoded from Kuf2Main.exe - they make the stage playable, they are not the original game's balance.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "KufUnit.generated.h"

class UStaticMesh;
class UStaticMeshComponent;

UCLASS()
class AKufUnit : public AActor
{
	GENERATED_BODY()

public:
	AKufUnit();

	// Set by the importer from the stage's group record (job = K2_JOB_TYPE name decoded from +448).
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Kuf")
	FString JobName;

	// 0 = player army, 1 = enemy. Placeholder rule: human jobs (H_*) are the player's, everything else is the enemy.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Kuf")
	int32 Team = 1;

	// True when Team came from the stage file (faction byte at +77 of the group record: 0 = the player's army); then InitFromJob keeps it.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Kuf")
	bool bTeamFromData = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Kuf")
	FString GroupName;

	UFUNCTION(BlueprintCallable, Category = "Kuf")
	void ApplyMesh(UStaticMesh* Mesh);

	UFUNCTION(BlueprintCallable, Category = "Kuf")
	void InitFromJob();

	void OrderMove(const FVector& Target);
	void OrderAttack(AKufUnit* Victim);
	void SetSelected(bool bSel) { bSelected = bSel; }
	bool IsSelected() const { return bSelected; }
	bool IsAlive() const { return Health > 0.0f; }

	float Health = 100.0f;
	float MaxHealth = 100.0f;
	float Speed = 450.0f;           // cm/s
	float AttackRange = 200.0f;
	float AttackDamage = 10.0f;
	float AttackInterval = 1.0f;
	float AggroRange = 2200.0f;

	// Counters used by the headless self-test (whole-session totals, survive unit death).
	float DamageDealt = 0.0f;
	float DistanceMoved = 0.0f;
	int32 Kills = 0;
	static double TotalDamage;
	static double TotalMoved;
	static int32 TotalKills;

	virtual void Tick(float DeltaSeconds) override;

protected:
	virtual void BeginPlay() override;

private:
	void SnapToGround();
	AKufUnit* FindNearestEnemy(float MaxDist) const;

	UPROPERTY()
	TObjectPtr<UStaticMeshComponent> Body;

	FVector MoveTarget = FVector::ZeroVector;
	bool bHasMove = false;
	TWeakObjectPtr<AKufUnit> Target;
	float Cooldown = 0.0f;
	float ScanTimer = 0.0f;
	bool bSelected = false;
	bool bOrdered = false;
};
